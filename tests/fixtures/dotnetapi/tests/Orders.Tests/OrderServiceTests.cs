using Xunit;

public class OrderServiceTests
{
    [Fact]
    public void FindRejectsZero() => Assert.Null(Orders.Api.OrderService.Find(0));
}
